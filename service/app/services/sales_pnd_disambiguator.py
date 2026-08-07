"""
sales_pnd_disambiguator.py — Deterministic PND product_code resolution.

Why
---
Sales packing lists for "Plain" pendants (PND) carry the literal token
``PND`` instead of a design number. When a single client invoice has
multiple PND lines (typical for mixed-metal pendant orders), the parser
cannot tell which sales row maps to which supplier-side product_code:
both rows have ``design_no="PND"``.

Heuristic
---------
Pair sales PND rows to supplier PND product_codes by ascending price.
Real-world signal: customers are billed at a markup that is fairly
consistent across lines from the same shipment, so the cheapest sales
PND corresponds to the cheapest supplier-side pendant. Verified for
AWB 6049349806:

    sales 5.13   supplier $4   ratio ≈ 1.28
    sales 51.30  supplier $36  ratio ≈ 1.43

Strict gates — disambiguation only fires when all hold:
  1. Sales rows share the same client_ref/invoice_no.
  2. Each sales row's design_no is exactly "PND" (case-insensitive).
  3. Supplier candidates are plain pendants from the same invoice
     (item_type starts with "PEND" — covers PENDANT/PEND/PND).
  4. Candidate count equals sales PND row count.
  5. All sales prices are pairwise distinct AND all supplier prices
     are pairwise distinct.

Any failure → leave the rows unresolved and emit a warning. The
existing manual-correction path (operator pins product_code via the
correction registry) remains the fallback.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def build_supplier_candidates(
    invoice_lines: List[Dict[str, Any]],
    packing_rows:  Optional[List[Dict[str, Any]]] = None,
    *,
    invoice_no:    str = "",
) -> List[Dict[str, Any]]:
    """Plain-pendant supplier candidates, sourced from the invoice authority.

    Candidate identity (``product_code``), price and item type all come from
    ``invoice_lines`` — the mint point of every product code, which always
    carries its own ``rate_usd``. Candidates must NOT be built from packing
    rows: a packing row's ``product_code`` is itself the *output* of the
    packing→invoice matcher, so sourcing candidates there makes the sales
    mapping inherit every purchase-side mis-assignment (and a NULL packing
    code poisons the whole candidate set). One invoice line = one candidate,
    regardless of how many packing rows were assigned to it — an aggregate
    N:1 assignment must not inflate the candidate count.

    ``packing_rows`` are corroborating evidence only: they may attach a
    ``design_no`` to a candidate (useful in warnings and operator review),
    but they never decide which candidates exist and never veto one.

    ``authority_qty`` carries the invoice-authorised quantity so the pairing
    step can refuse a sales demand that exceeds it.
    """
    from .invoice_packing_extractor import _canonical_item_type

    design_by_code: Dict[str, str] = {}
    for pl in packing_rows or []:
        pc = str(pl.get("product_code") or "").strip()
        dn = str(pl.get("design_no") or "").strip()
        if pc and dn:
            design_by_code.setdefault(pc, dn)

    out: List[Dict[str, Any]] = []
    for il in invoice_lines or []:
        if invoice_no and str(il.get("invoice_no") or "").strip() != invoice_no:
            continue
        item_type = _canonical_item_type(
            str(il.get("item_type") or il.get("description") or "")
        ).upper()
        if not (item_type.startswith("PEND") or item_type == "PND"):
            continue
        pc = str(il.get("product_code") or "").strip()
        out.append({
            "product_code":  pc,
            "design_no":     design_by_code.get(pc, ""),
            "item_type":     item_type,
            "unit_price":    float(il.get("rate_usd") or il.get("unit_price") or 0),
            "authority_qty": float(il.get("quantity") or 0),
        })
    return out


def disambiguate_pnd(
    sales_rows:           List[Dict[str, Any]],
    supplier_candidates:  List[Dict[str, Any]],
    *,
    invoice_no:           str = "",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Walk *sales_rows*; for every row whose design_no == "PND" pair it to
    a supplier candidate by ascending price.

    Inputs
    ------
    sales_rows
        List of dicts as parsed from the sales packing list. Each dict
        is mutated in-place when disambiguation fires:
          - ``design_no`` is left as "PND" (operator-visible signal that
            the original token was opaque)
          - ``product_code`` is set to the matched supplier code
          - ``pnd_mapping_source = "price_tiebreak"`` is stamped
        Rows whose design_no != "PND" are returned unchanged.

    supplier_candidates
        Plain-pendant product_codes from the matched invoice, each as
        ``{"product_code": str, "unit_price": float, "item_type": str,
            "design_no": str, "authority_qty": float}``. Built by
        ``build_supplier_candidates()`` from ``invoice_lines`` — the
        authority — with packing rows as corroborating evidence only.
        ``authority_qty`` is optional; when present, a sales row demanding
        more than it is refused rather than paired.

    invoice_no
        Optional — for warning messages.

    Returns
    -------
    (mutated_sales_rows, summary)
        ``summary`` shape::

            {
              "applied":           bool,
              "reason":            str,            # explanation of decision
              "pairs":             [{ "sales_unit_price": float,
                                       "product_code":     str }],
              "warnings":          [str],
            }
    """
    summary: Dict[str, Any] = {
        "applied":  False,
        "reason":   "",
        "pairs":    [],
        "warnings": [],
    }

    pnd_sales = [r for r in sales_rows
                 if str(r.get("design_no", "") or "").strip().upper() == "PND"]

    if not pnd_sales:
        summary["reason"] = "no PND sales rows"
        return sales_rows, summary

    # Gate 3 — supplier candidates must be plain pendants. We accept any
    # item_type that begins with PEND (PENDANT, PEND, …) or the abbreviation
    # PND used in some EJL templates.
    def _is_pendant(it: str) -> bool:
        u = (it or "").strip().upper()
        return u.startswith("PEND") or u == "PND"
    pendants = [c for c in supplier_candidates
                if _is_pendant(c.get("item_type", ""))]

    # Gate 4 — counts must match.
    if len(pendants) != len(pnd_sales):
        summary["reason"] = (
            f"PND count mismatch (sales={len(pnd_sales)}, "
            f"supplier_pendants={len(pendants)})"
            + (f" for invoice {invoice_no!r}" if invoice_no else "")
        )
        summary["warnings"].append(summary["reason"])
        return sales_rows, summary

    # Gate 5 — distinct prices on both sides (strict: any tie blocks).
    sales_prices    = [float(r.get("unit_price", 0) or 0) for r in pnd_sales]
    supplier_prices = [float(c.get("unit_price", 0) or 0) for c in pendants]
    if len(set(sales_prices)) != len(sales_prices):
        summary["reason"] = ("sales-side PND prices not pairwise distinct "
                             f"({sales_prices}) — refusing to guess")
        summary["warnings"].append(summary["reason"])
        return sales_rows, summary
    if len(set(supplier_prices)) != len(supplier_prices):
        summary["reason"] = ("supplier-side PND prices not pairwise distinct "
                             f"({supplier_prices}) — refusing to guess")
        summary["warnings"].append(summary["reason"])
        return sales_rows, summary
    if any(p <= 0 for p in sales_prices + supplier_prices):
        summary["reason"] = "non-positive price detected — refusing to guess"
        summary["warnings"].append(summary["reason"])
        return sales_rows, summary

    # Sort both sides ascending. Pair index-by-index → deterministic.
    sales_sorted    = sorted(pnd_sales, key=lambda r: float(r.get("unit_price", 0) or 0))
    supplier_sorted = sorted(pendants,  key=lambda c: float(c.get("unit_price", 0) or 0))

    pairs: List[Dict[str, Any]] = []
    staged: List[Tuple[Dict[str, Any], Dict[str, Any], str]] = []
    for s_row, sup in zip(sales_sorted, supplier_sorted):
        pc = (sup.get("product_code") or "").strip()
        if not pc:
            summary["reason"] = "supplier candidate missing product_code"
            summary["warnings"].append(summary["reason"])
            return sales_rows, summary
        # Authority-quantity gate: a pairing may never promise more pieces
        # than the invoice line authorises. Refusing here leaves the row for
        # the manual-correction path instead of inventing availability the
        # over-bill gate would then have to catch downstream.
        cap = float(sup.get("authority_qty", 0) or 0)
        s_qty = float(s_row.get("quantity", 0) or 0)
        if cap and s_qty > cap + 1e-9:
            summary["reason"] = (
                f"sales PND qty {s_qty:g} exceeds invoice authority {cap:g} "
                f"for {pc!r} — refusing to guess"
            )
            summary["warnings"].append(summary["reason"])
            return sales_rows, summary
        staged.append((s_row, sup, pc))
    # Mutate only after every pair passed every gate — a refusal must leave
    # all rows exactly as they arrived, never a half-applied pairing.
    for s_row, sup, pc in staged:
        s_row["product_code"]        = pc
        s_row["pnd_mapping_source"]  = "price_tiebreak"
        pairs.append({
            "sales_unit_price":  float(s_row.get("unit_price", 0) or 0),
            "supplier_unit_price": float(sup.get("unit_price", 0) or 0),
            "product_code":      pc,
        })

    summary["applied"] = True
    summary["reason"]  = (f"paired {len(pairs)} PND row(s) by ascending price"
                          + (f" for invoice {invoice_no!r}" if invoice_no else ""))
    summary["pairs"]   = pairs
    return sales_rows, summary
