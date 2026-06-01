"""
proforma_draft_governance.py — Creation-time and lifecycle governance rules
for Proforma Drafts.

All public functions are **no-ops when the flag is off** (default). The flag
``settings.proforma_draft_governance_enabled`` gates every check so existing
stored drafts and current inputs are NEVER affected until an operator explicitly
enables governance.

Governance is WRITE-PATH only:
    create   : validate each line's design_no format and hs_code (if provided)
    line patch: validate hs_code format and unit_price sign
    top patch : validate buyer_override / ship_to_override schema and currency
    post      : every line must carry a non-empty hs_code (customs requirement)
    convert   : series_id fallback must resolve to a non-"0" value

READ paths (GET, list, full draft serialisation) are NEVER called here.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..core.config import settings as _settings


# ── Regex constants ───────────────────────────────────────────────────────────

_HS_RE        = re.compile(r"^\d{6,10}$")         # 6–10 digit HS / HSN code
_CURRENCY_RE  = re.compile(r"^[A-Z]{3}$")         # ISO 4217 three-letter code
_DESIGN_NO_RE = re.compile(r"^[A-Za-z0-9\-_/\. ]{1,128}$")  # printable, ≤128

# Minimum required keys when a buyer/ship_to override is non-empty
_BUYER_REQUIRED = ("name",)

# Allowed top-level keys in buyer/ship-to overrides
_OVERRIDE_ALLOWED_KEYS = frozenset({
    "name", "street", "city", "zip", "country",
    "nip", "vat_eu", "email", "phone",
})


# ── Guard helper ──────────────────────────────────────────────────────────────

def _enabled() -> bool:
    """Return True iff governance is currently active."""
    return bool(_settings.proforma_draft_governance_enabled)


# ── Public validators ─────────────────────────────────────────────────────────

def check_creation_lines(lines: List[Dict[str, Any]]) -> None:
    """Validate the editable-lines list supplied at draft-creation time.

    Skips silently when governance is off.
    Raises ValueError with a clear message on the first violation.
    Rules:
      - product_code must be non-empty
      - design_no, if provided, must match the printable-alphanum pattern (≤128 chars)
      - hs_code, if provided, must be 6–10 digits
      - qty and unit_price must be non-negative numbers
    """
    if not _enabled():
        return

    for i, ln in enumerate(lines or []):
        idx = i + 1  # 1-based for human-readable errors
        pc = str(ln.get("product_code") or "").strip()
        if not pc:
            raise ValueError(
                f"line {idx}: product_code is required"
            )
        dn = str(ln.get("design_no") or "").strip()
        if dn and not _DESIGN_NO_RE.match(dn):
            raise ValueError(
                f"line {idx}: design_no {dn!r} contains invalid characters "
                f"or exceeds 128 characters — use alphanumeric + - _ / . space"
            )
        hs = str(ln.get("hs_code") or ln.get("hsn_code") or "").strip()
        if hs and not _HS_RE.match(hs):
            raise ValueError(
                f"line {idx}: hs_code {hs!r} must be 6–10 digits "
                f"(e.g. '711319' or '71131900')"
            )
        raw_qty = ln.get("qty", ln.get("quantity", 0))
        try:
            qty_v = float(raw_qty or 0)
        except (TypeError, ValueError):
            raise ValueError(f"line {idx}: qty must be a number, got {raw_qty!r}")
        if qty_v < 0:
            raise ValueError(f"line {idx}: qty must be ≥ 0")
        raw_up = ln.get("unit_price", 0)
        try:
            up_v = float(raw_up or 0)
        except (TypeError, ValueError):
            raise ValueError(f"line {idx}: unit_price must be a number, got {raw_up!r}")
        if up_v < 0:
            raise ValueError(f"line {idx}: unit_price must be ≥ 0")


def check_line_patch(patch: Dict[str, Any]) -> None:
    """Validate the fields in a single-line PATCH body.

    Skips silently when governance is off.
    Raises ValueError on violation.
    """
    if not _enabled():
        return

    hs = str(patch.get("hs_code") or "").strip()
    if hs and not _HS_RE.match(hs):
        raise ValueError(
            f"hs_code {hs!r} must be 6–10 digits (e.g. '711319')"
        )
    for field in ("qty", "unit_price"):
        if field in patch:
            try:
                v = float(patch[field] or 0)
            except (TypeError, ValueError):
                raise ValueError(f"{field} must be a number, got {patch[field]!r}")
            if v < 0:
                raise ValueError(f"{field} must be ≥ 0")


def check_top_patch(patch: Dict[str, Any]) -> None:
    """Validate top-level draft PATCH fields: currency, buyer_override, ship_to_override.

    Skips silently when governance is off.
    Raises ValueError on violation.
    """
    if not _enabled():
        return

    currency = str(patch.get("currency") or "").strip().upper()
    if currency and not _CURRENCY_RE.match(currency):
        raise ValueError(
            f"currency {currency!r} must be a 3-letter ISO 4217 code (e.g. EUR, USD)"
        )

    for field in ("buyer_override", "ship_to_override"):
        override = patch.get(field)
        if override is None:
            continue
        if not isinstance(override, dict):
            raise ValueError(f"{field} must be a JSON object, got {type(override).__name__!r}")
        bad_keys = set(override) - _OVERRIDE_ALLOWED_KEYS
        if bad_keys:
            raise ValueError(
                f"{field} contains unknown keys: {sorted(bad_keys)!r}. "
                f"Allowed: {sorted(_OVERRIDE_ALLOWED_KEYS)!r}"
            )
        if override:  # non-empty override must have a name
            for req in _BUYER_REQUIRED:
                if not (override.get(req) or "").strip():
                    raise ValueError(f"{field}: '{req}' is required when override is non-empty")


def check_post_readiness(lines: List[Dict[str, Any]]) -> None:
    """Validate hs_code presence on every line before wFirma POST.

    HS codes are required on EU commercial invoices / customs declarations.
    Skips silently when governance is off.
    Raises ValueError listing all lines missing hs_code.
    """
    if not _enabled():
        return

    missing = [
        i + 1
        for i, ln in enumerate(lines or [])
        if not str(ln.get("hs_code") or ln.get("hsn_code") or "").strip()
    ]
    if missing:
        raise ValueError(
            f"governance: hs_code is required on all lines before posting to wFirma "
            f"(missing on line(s) {missing}). Add HS codes via PATCH /draft/{{id}}/lines/{{lid}}."
        )


def check_convert_series(series_id: Optional[str]) -> None:
    """Validate the resolved invoice series_id before convert.

    ADR-027 D6 (step 3): an empty series_id is NOW VALID — the caller
    omits ``<series>`` and wFirma applies its own contractor default.
    This function therefore passes silently for empty / None values.

    Raises ValueError (when governance is on) only for the literal "0"
    sentinel, which would produce a malformed ``<series><id>0</id></series>``
    element and is never a valid operator choice.

    Skips silently when governance is off.
    """
    if not _enabled():
        return

    sid = (series_id or "").strip()
    if sid == "0":
        raise ValueError(
            "governance: invoice series_id resolved to '0' which is not a "
            "valid wFirma series — supply final_series_id in the request "
            "body or set preferred_invoice_series_id on the customer master"
        )
