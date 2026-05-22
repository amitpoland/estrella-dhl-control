"""wfirma_product_compare.py — pure comparison of wFirma product vs local
expectation, for the search-first / compare / ask-before-adopt workflow.

This module is the FOUNDATION layer of the search-first product authority
workflow (operator-stated 2026-05-23):

    Product required
          ↓
    Search wFirma by product_code        ← already in wfirma_product_auto_register
          ↓
    Found?
     ├─ Yes → adopt existing product
     │         compare metadata          ← THIS MODULE
     │         ask before update/overwrite ← future PR
     │
     └─ No  → create product             ← already in wfirma_product_auto_register

The existing ``wfirma_product_auto_register._register_one`` silently
persists a matched-status mapping the instant wFirma search returns a
hit (lines 205-256 of that module). That silent auto-adoption is what
prevents operators from seeing metadata drift between local expectation
and the wFirma side. It also makes "ask before update/overwrite"
impossible because there's no comparison surface to ask against.

This module is **pure, side-effect-free**: it takes a ``WFirmaProduct``
(live API response) and a ``local_expected`` dict (what the system
believed the product should look like — typically derived from packing /
invoice lines and existing local cache), and returns a structured
comparison report. The report classifies each field as identical, minor
drift (whitespace / case), or material drift, and emits a recommendation
the operator UI / downstream endpoint can act on:

    * ``adopt_as_is``       — adopt the wFirma record verbatim; no update
    * ``adopt_with_warning``— identical-enough; adopt but log advisory
    * ``operator_review``   — material drift; operator must decide
    * ``no_local_context``  — no local expectation provided; nothing to compare

The function NEVER writes to wfirma_products, wfirma_customers, or any
other persistence layer. It is callable from read-only contexts (preview
endpoints, dry-run scans, dashboard inspectors) and from the future
``/adopt`` write endpoints that will gate adoption on operator confirmation.

Out of scope for this module (future PRs):
    * The HTTP endpoints that consume this comparison
    * The actual /adopt, /update-and-adopt, /create write flows
    * Modification of ``_register_one`` to suppress silent auto-adoption
    * Frontend modal for operator confirmation

This module addresses ONLY the "compare metadata" sub-step.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Optional


# ── normalisation helpers ───────────────────────────────────────────────────


def _normalise_text(s: Any) -> str:
    """Whitespace-collapsed, case-insensitive comparison key.

    Mirrors the normaliser pattern used by ``customer_resolution_authority.
    _normalize_name`` so all authority modules share consistent comparison
    semantics. Returns ``""`` for None / non-string inputs.
    """
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    return " ".join(s.strip().split()).lower()


def _normalise_unit(s: Any) -> str:
    """Unit normalisation — wFirma stores 'szt.' / 'pcs' / 'kpl' as TEXT;
    the trailing dot and whitespace are noise. Lowercase + strip + trailing-dot
    removal makes comparison robust to operator-typed variants."""
    n = _normalise_text(s)
    return n.rstrip(".") if n.endswith(".") else n


# ── core comparison ────────────────────────────────────────────────────────


def compare_product_metadata(
    *,
    wfirma_product: Optional[Any],   # WFirmaProduct or None
    local_expected: Optional[Dict[str, Any]],
    product_code: str,
) -> Dict[str, Any]:
    """Compare a live ``WFirmaProduct`` against the system's local expectation.

    Args:
        wfirma_product:  Live wFirma response (the dataclass returned by
            ``wfirma_client.get_product_by_code``) OR ``None`` if wFirma
            does not have a product for this code.
        local_expected:  Dict describing what the local system thought
            the product should look like. Keys consumed by this comparator
            (all optional):
                * ``product_code``    — the code the local layer queried for
                * ``name_pl``         — expected Polish display name
                * ``unit``            — expected unit (szt., pcs, kpl, ...)
                * ``vat_rate``        — expected VAT rate (TEXT, e.g. "23")
            Any extra keys are ignored; missing keys are treated as
            "no local expectation for this field" and skipped from the
            diff (cannot drift against an absent expectation).
        product_code:    The product_code under inspection (used for
            recommendation context + correlation in the response).

    Returns:
        Structured comparison dict::

            {
              "product_code":            <str>,
              "wfirma_present":          <bool>,
              "wfirma_product_id":       <str> | "",
              "wfirma_code":             <str> | "",
              "local_present":           <bool>,
              "identical":               <bool>,   # only meaningful when both present
              "differences":             [          # one entry per field with drift
                  {
                      "field":           "name" | "unit" | "code",
                      "local":           <raw local value>,
                      "wfirma":          <raw wfirma value>,
                      "severity":        "minor" | "material",
                      "normalised_match":<bool>,  # True when only whitespace/case differs
                  }, ...
              ],
              "recommendation":          "adopt_as_is" | "adopt_with_warning"
                                          | "operator_review" | "create_new"
                                          | "no_local_context",
              "advisory":                <str>,    # human-readable summary
              "wfirma_stock":            {         # informational only — wFirma side
                  "count":     <float>,
                  "reserved":  <float>,
                  "available": <float>,
              } | None,
            }

    Pure read function. No I/O. No persistence. Safe for read-only
    preview endpoints and write-side ask-before-confirm flows alike.
    """
    out: Dict[str, Any] = {
        "product_code":      product_code,
        "wfirma_present":    wfirma_product is not None,
        "wfirma_product_id": "",
        "wfirma_code":       "",
        "local_present":     bool(local_expected),
        "identical":         False,
        "differences":       [],
        "recommendation":    "no_local_context",
        "advisory":          "",
        "wfirma_stock":      None,
    }

    # ── Case 1: wFirma has no product for this code ──────────────────────
    if wfirma_product is None:
        out["recommendation"] = "create_new"
        out["advisory"] = (
            f"wFirma has no product for code {product_code!r}. "
            f"Operator may create after explicit confirmation "
            f"(requires WFIRMA_CREATE_PRODUCT_ALLOWED)."
        )
        return out

    # Extract wFirma-side identity safely whether we got a dataclass or
    # a duck-typed object (test stubs may pass a dict or SimpleNamespace).
    def _g(obj, attr, default=""):
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    wfirma_id   = (_g(wfirma_product, "wfirma_id", "") or "").strip()
    wfirma_name = (_g(wfirma_product, "name", "") or "")
    wfirma_code = (_g(wfirma_product, "code", "") or "")
    wfirma_unit = (_g(wfirma_product, "unit", "") or "")
    wfirma_cnt  = _g(wfirma_product, "count", 0.0) or 0.0
    wfirma_rsv  = _g(wfirma_product, "reserved", 0.0) or 0.0

    out["wfirma_product_id"] = wfirma_id
    out["wfirma_code"]       = wfirma_code
    out["wfirma_stock"] = {
        "count":     float(wfirma_cnt),
        "reserved":  float(wfirma_rsv),
        "available": max(0.0, float(wfirma_cnt) - float(wfirma_rsv)),
    }

    # ── Case 2: wFirma has it but no local expectation to compare against ──
    if not local_expected:
        out["recommendation"] = "no_local_context"
        out["advisory"] = (
            f"wFirma has product {wfirma_id!r} (name={wfirma_name!r}) for "
            f"code {product_code!r}, but no local expected metadata was "
            f"supplied — nothing to compare. Operator may adopt the wFirma "
            f"record verbatim after confirmation."
        )
        return out

    # ── Case 3: wFirma found + local expectation present → diff each field ──
    diffs = []

    def _diff_field(field: str, local: Any, wf: Any, normaliser=_normalise_text):
        """Append a diff entry when values differ.

        Severity ladder:
          * raw values equal                       → no diff (skip)
          * normalised (case+whitespace) equal     → minor drift
          * normalised differ                      → material drift
        """
        if local is None:
            return  # caller had no expectation for this field — skip
        if str(local) == str(wf):
            return  # truly identical, no diff at all
        n_local = normaliser(local)
        n_wf    = normaliser(wf)
        if n_local == n_wf:
            # Same normalised key but raw values differ (whitespace / case
            # / trailing dot etc.) — minor drift, operator-informational.
            diffs.append({
                "field":            field,
                "local":            local,
                "wfirma":           wf,
                "severity":         "minor",
                "normalised_match": True,
            })
            return
        # Material drift
        diffs.append({
            "field":            field,
            "local":            local,
            "wfirma":           wf,
            "severity":         "material",
            "normalised_match": False,
        })

    _diff_field("name", local_expected.get("name_pl"), wfirma_name)
    _diff_field("unit", local_expected.get("unit"),    wfirma_unit, _normalise_unit)
    # Code drift is rare but possible (operator typed the wrong code OR
    # wFirma normalised). Compare normalised.
    _diff_field("code", local_expected.get("product_code") or product_code,
                wfirma_code)

    out["differences"] = diffs

    # ── Classify recommendation ────────────────────────────────────────────
    has_material = any(d["severity"] == "material" for d in diffs)
    has_minor    = any(d["severity"] == "minor"    for d in diffs)

    if not diffs:
        out["identical"]      = True
        out["recommendation"] = "adopt_as_is"
        out["advisory"] = (
            f"wFirma product {wfirma_id!r} matches local expectation exactly. "
            f"Safe to adopt verbatim."
        )
    elif has_material:
        out["recommendation"] = "operator_review"
        fields = ", ".join(sorted({d["field"] for d in diffs if d["severity"] == "material"}))
        out["advisory"] = (
            f"wFirma product {wfirma_id!r} differs materially from local "
            f"expectation on field(s): {fields}. Operator must review and "
            f"decide between adopt-as-is, update-wFirma-then-adopt, or "
            f"create-new (requires WFIRMA_PRODUCT_UPDATE_ALLOWED for update)."
        )
    elif has_minor:
        out["recommendation"] = "adopt_with_warning"
        out["advisory"] = (
            f"wFirma product {wfirma_id!r} matches local expectation modulo "
            f"whitespace/case. Safe to adopt; the local cache will reflect "
            f"wFirma's canonical formatting."
        )

    return out


__all__ = ["compare_product_metadata"]
