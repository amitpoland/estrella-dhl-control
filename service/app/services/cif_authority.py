"""
cif_authority.py — the single backend gate for "may this customs/PZ action run?"

This module is the action-layer companion to ``cif_resolver.resolve_cif``. The
resolver answers a pure question ("what is the customs CIF, and how confident
are we?"); this module turns that tri-state answer into a *decision* that every
customs-adjacent endpoint shares, so no route, generator, PZ step, or DHL step
makes its own independent CIF call.

The governance rule it enforces (operator directive, 2026-06-17):

    Raw parsed invoice fields are EVIDENCE. ``clearance_decision`` /
    ``resolve_cif`` is AUTHORITY. No action may independently rely on a raw
    invoice CIF of 0 when an authoritative layer (AWB Custom Val, OCR/AI
    fallback, verification snapshot, …) has resolved a usable customs value.

Two public functions:

``get_cif_authority(audit)``
    Pure, never raises. Returns a flat dict mirroring the frontend
    ``getResolvedCifAuthority`` helper — the resolved value, its tri-state, its
    source, the raw invoice CIF (advisory), and the boolean ``is_resolved`` /
    ``is_blocked`` flags + a human ``blocker_reason``. Use this when an endpoint
    needs to *read* the authority (e.g. action-proposal routing gates) without
    necessarily rejecting the request.

``require_resolved_cif(audit, action=...)``
    The gate. Returns the same dict on RESOLVED. Raises ``HTTPException(422)``
    on UNKNOWN (extraction gap — block safely, surface the next action) and on
    DECLARED_ZERO (a genuine declared zero still requires explicit operator
    review before a customs/PZ document is generated against a zero value).

Neither function ever writes, mutates the audit, or fabricates a 0.0.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException

from .cif_resolver import (
    CIF_DECLARED_ZERO,
    CIF_RESOLVED,
    CIF_UNKNOWN,
    resolve_cif,
)

# Stable machine codes surfaced on the HTTPException detail so the frontend /
# callers can branch on the *reason* a customs action is blocked, not parse
# prose. ``cif_unresolved`` is kept byte-identical to the code #633 shipped on
# the Polish-description route so existing clients and tests are unaffected.
CODE_CIF_UNRESOLVED:    str = "cif_unresolved"
CODE_CIF_DECLARED_ZERO: str = "cif_declared_zero"


def get_cif_authority(audit: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the customs CIF authority for an audit, as a flat decision dict.

    Pure. Never raises. Never writes. Mirrors the frontend
    ``getResolvedCifAuthority`` field set so the backend gate and the UI read
    the same shape.

    Returns
    -------
    dict::

        {
          "cif_usd":              float | None,   # None only when unknown
          "cif_state":            "resolved" | "declared_zero" | "unknown",
          "cif_source":           str,            # winning layer, or "unavailable"
          "invoice_cif_parsed":   float | None,   # raw invoice CIF — EVIDENCE only
          "invoice_cif_advisory": bool,           # True when raw invoice CIF is
                                                  # present but NOT the authority
          "is_resolved":          bool,
          "is_blocked":           bool,           # True for unknown OR declared_zero
          "blocker_reason":       str | None,     # human reason when blocked
          "extraction_gap":       dict | None,    # resolver gap marker (unknown)
        }
    """
    audit = audit or {}
    res = resolve_cif(audit)

    cif_state = res.get("cif_state")
    cif_usd = res.get("cif_usd")
    cif_source = res.get("cif_source")
    gap = res.get("extraction_gap") or None

    # Raw invoice CIF is evidence only — surfaced for display, never the gate.
    invoice_totals = audit.get("invoice_totals") or {}
    raw_invoice_cif = invoice_totals.get("total_cif_usd")
    try:
        invoice_cif_parsed: Optional[float] = (
            float(raw_invoice_cif) if raw_invoice_cif is not None else None
        )
    except (TypeError, ValueError):
        invoice_cif_parsed = None

    is_resolved = cif_state == CIF_RESOLVED
    is_blocked = not is_resolved

    # The raw invoice CIF is "advisory" whenever it is present but is NOT what
    # resolved the authority (e.g. invoice CIF 0 while the AWB Custom Val won).
    invoice_cif_advisory = (
        invoice_cif_parsed is not None
        and cif_source != "invoice_totals.total_cif_usd"
    )

    blocker_reason: Optional[str] = None
    if cif_state == CIF_UNKNOWN:
        blocker_reason = (gap or {}).get("reason") or (
            "Customs CIF value could not be resolved from any authority "
            "(invoice totals, DHL pre-check, AWB Custom Val, or OCR/AI fallback)."
        )
    elif cif_state == CIF_DECLARED_ZERO:
        blocker_reason = (
            "Customs value is explicitly declared zero "
            f"(source: {cif_source}); operator review is required before a "
            "customs/PZ document may be generated against a zero value."
        )

    return {
        "cif_usd":              cif_usd,
        "cif_state":            cif_state,
        "cif_source":           cif_source,
        "invoice_cif_parsed":   invoice_cif_parsed,
        "invoice_cif_advisory": invoice_cif_advisory,
        "is_resolved":          is_resolved,
        "is_blocked":           is_blocked,
        "blocker_reason":       blocker_reason,
        "extraction_gap":       gap,
    }


def require_resolved_cif(
    audit: Dict[str, Any],
    *,
    action: str = "this customs action",
) -> Dict[str, Any]:
    """Gate a customs/PZ action on a RESOLVED customs CIF.

    Returns the ``get_cif_authority`` dict (with a positive ``cif_usd``) when the
    customs value is RESOLVED. Otherwise raises ``HTTPException(422)`` with a
    machine ``code`` and the resolver provenance:

      - UNKNOWN       → ``code = "cif_unresolved"``    (extraction gap; block
                        safely, surface the next action to take)
      - DECLARED_ZERO → ``code = "cif_declared_zero"`` (genuine zero requires
                        explicit operator review before generating a document)

    Parameters
    ----------
    audit : dict
        The shipment audit record.
    action : str
        Human label for the gated action, woven into the error message
        (e.g. "a Polish customs description", "a DSK broker notification").
    """
    info = get_cif_authority(audit)
    state = info["cif_state"]

    if state == CIF_RESOLVED:
        # The resolver's contract guarantees a positive ``cif_usd`` on RESOLVED
        # (a zero is DECLARED_ZERO, an absence is UNKNOWN). Treat a non-positive
        # value here as a resolver contract violation rather than silently
        # re-routing it to the "unresolved" branch — that would mask the real
        # fault and emit a misleading extraction-gap message.
        cif_usd = info["cif_usd"]
        if cif_usd is None or float(cif_usd) <= 0:
            raise HTTPException(
                status_code=500,
                detail={
                    "guard":      "cif_authority_contract",
                    "error":     (
                        "CIF resolver returned state=resolved with a "
                        f"non-positive value ({cif_usd!r}) — resolver contract "
                        "violation."
                    ),
                    "code":       "cif_resolved_contract_violation",
                    "cif_state":  state,
                    "cif_source": info["cif_source"],
                },
            )
        return info

    if state == CIF_DECLARED_ZERO:
        raise HTTPException(
            status_code=422,
            detail={
                "guard":      CODE_CIF_DECLARED_ZERO,
                "error":     (
                    f"Customs value is explicitly declared zero for this "
                    f"shipment. Generating {action} against a zero customs "
                    f"value requires explicit operator review."
                ),
                "code":       CODE_CIF_DECLARED_ZERO,
                "cif_state":  state,
                "cif_source": info["cif_source"],
                "hint":      (
                    "Confirm this is a genuine no-commercial-value shipment and "
                    "complete operator review, or correct the customs value, "
                    f"before generating {action}."
                ),
            },
        )

    # UNKNOWN (or any non-resolved residue) — extraction gap.
    gap = info.get("extraction_gap") or {}
    raise HTTPException(
        status_code=422,
        detail={
            "guard":      CODE_CIF_UNRESOLVED,
            "error":     (
                f"Customs CIF value could not be resolved from any authority "
                f"(invoice totals, DHL pre-check, AWB Custom Val, or OCR/AI "
                f"fallback). Generating {action} without a resolved customs "
                f"value would produce an invalid document."
            ),
            "code":       CODE_CIF_UNRESOLVED,
            "cif_state":  state,
            "cif_source": info["cif_source"],
            "hint":       gap.get("next_action")
                          or (
                              "Re-process the batch with valid invoice PDFs, or "
                              "confirm the AWB customs value, before generating "
                              f"{action}."
                          ),
        },
    )
